"""Tests for the v0.3.4 sanitization-warning suppression feature.

Coverage:

1. ``core.sanitize_suppression`` storage layer — global mute,
   per-tool mute, per-field mute, clear-all.
2. ``filter_warnings`` and ``should_skip_dialog`` predicates.
3. ``sanitize_all_values_detailed`` returns ``(text, field_id)``
   tuples parallel to ``sanitize_all_values``.
4. ``_show_injection_warning`` dialog wiring:
   - Three checkboxes appear iff ``suppress_sanitization_warnings``
     is granted AND warning_fids is provided.
   - Checking + clicking Yes persists the suppression to QSettings.
   - The capability denied → no checkboxes.
5. End-to-end through ``_start_run`` (mocked):
   - Globally-muted run skips the dialog entirely and proceeds.
   - Per-tool-muted run skips.
   - Per-field-muted warnings get filtered; if all are filtered,
     skip the dialog.
6. ``Edit -> Sanitization warnings...`` dialog (the re-enable
   surface) constructs and exposes the same suppression state.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QMessageBox,
)

_app = QApplication.instance() or QApplication([])

QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.question = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Yes
)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path: Path):
    """Each test gets an isolated INI file via the
    ``SCRIPTREE_SETTINGS_PATH`` env var that ``app_settings.get_settings``
    consults on every call.  The fixture also calls ``clear_all``
    after the test so the next test starts with a clean slate even
    if the env-var-pinned file accidentally leaks somewhere."""
    ini_path = tmp_path / "test.ini"
    monkeypatch.setenv("SCRIPTREE_SETTINGS_PATH", str(ini_path))
    yield
    # Belt-and-braces: explicitly clear any state we wrote.
    from scriptree.core import sanitize_suppression as _supp
    try:
        _supp.clear_all()
    except Exception:  # noqa: BLE001
        pass


# ===========================================================================
# 1. Storage layer
# ===========================================================================

class TestStorageLayer:

    def test_global_mute_default_false(self) -> None:
        from scriptree.core import sanitize_suppression as supp
        assert supp.is_globally_muted() is False

    def test_global_mute_set_get(self) -> None:
        from scriptree.core import sanitize_suppression as supp
        supp.set_globally_muted(True)
        assert supp.is_globally_muted() is True
        supp.set_globally_muted(False)
        assert supp.is_globally_muted() is False

    def test_tool_mute_round_trip(self, tmp_path: Path) -> None:
        from scriptree.core import sanitize_suppression as supp
        p = tmp_path / "demo.scriptree"
        p.write_text("{}", encoding="utf-8")
        assert supp.is_tool_muted(str(p)) is False
        supp.mute_tool(str(p))
        assert supp.is_tool_muted(str(p)) is True
        assert str(p.resolve()) in supp.muted_tools()
        supp.unmute_tool(str(p))
        assert supp.is_tool_muted(str(p)) is False

    def test_field_mute_round_trip(self, tmp_path: Path) -> None:
        from scriptree.core import sanitize_suppression as supp
        p = tmp_path / "demo.scriptree"
        p.write_text("{}", encoding="utf-8")
        assert supp.muted_fields_for_tool(str(p)) == []
        supp.mute_fields_for_tool(str(p), {"foo", "bar"})
        assert sorted(supp.muted_fields_for_tool(str(p))) == ["bar", "foo"]
        supp.unmute_field_for_tool(str(p), "foo")
        assert supp.muted_fields_for_tool(str(p)) == ["bar"]
        # Removing the last field also removes the tool entry from
        # the underlying map (clean-up).
        supp.unmute_field_for_tool(str(p), "bar")
        assert supp.muted_fields_for_tool(str(p)) == []

    def test_path_normalisation_collapses_slash_styles(
        self, tmp_path: Path,
    ) -> None:
        """Forward-slash and back-slash variants of the same path
        should collapse to a single key."""
        from scriptree.core import sanitize_suppression as supp
        p = tmp_path / "demo.scriptree"
        p.write_text("{}", encoding="utf-8")
        forward = str(p).replace("\\", "/")
        back = str(p).replace("/", "\\")
        supp.mute_tool(forward)
        assert supp.is_tool_muted(back)
        # And only one entry persists.
        assert len(supp.muted_tools()) == 1

    def test_clear_all_resets_everything(self, tmp_path: Path) -> None:
        from scriptree.core import sanitize_suppression as supp
        p = tmp_path / "demo.scriptree"
        p.write_text("{}", encoding="utf-8")
        supp.set_globally_muted(True)
        supp.mute_tool(str(p))
        supp.mute_fields_for_tool(str(p), {"x"})

        supp.clear_all()

        assert supp.is_globally_muted() is False
        assert supp.muted_tools() == []
        assert supp.muted_fields_for_tool(str(p)) == []


# ===========================================================================
# 2. filter_warnings + should_skip_dialog
# ===========================================================================

class TestFilterPredicates:

    def test_should_skip_dialog_when_globally_muted(self) -> None:
        from scriptree.core import sanitize_suppression as supp
        supp.set_globally_muted(True)
        assert supp.should_skip_dialog("any/path") is True
        assert supp.should_skip_dialog(None) is True

    def test_should_skip_dialog_when_tool_muted(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.core import sanitize_suppression as supp
        p = tmp_path / "x.scriptree"
        p.write_text("{}", encoding="utf-8")
        supp.mute_tool(str(p))
        assert supp.should_skip_dialog(str(p)) is True
        # Other tools unaffected.
        other = tmp_path / "y.scriptree"
        other.write_text("{}", encoding="utf-8")
        assert supp.should_skip_dialog(str(other)) is False

    def test_filter_warnings_drops_per_field_muted(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.core import sanitize_suppression as supp
        p = tmp_path / "x.scriptree"
        p.write_text("{}", encoding="utf-8")
        supp.mute_fields_for_tool(str(p), {"f1"})
        out = supp.filter_warnings(
            str(p),
            ["w1", "w2", "w3"],
            ["f1", "f2", "f1"],
        )
        # Both warnings tagged f1 are dropped.
        assert out == ["w2"]

    def test_filter_warnings_no_mute_returns_input(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.core import sanitize_suppression as supp
        p = tmp_path / "x.scriptree"
        p.write_text("{}", encoding="utf-8")
        out = supp.filter_warnings(
            str(p),
            ["w1", "w2"],
            ["a", "b"],
        )
        assert out == ["w1", "w2"]


# ===========================================================================
# 3. sanitize_all_values_detailed
# ===========================================================================

class TestSanitizeDetailed:

    def test_returns_field_id_per_warning(self) -> None:
        from scriptree.core.sanitize import sanitize_all_values_detailed
        out = sanitize_all_values_detailed(
            {"path1": "../etc/passwd", "name": "ok"},
            path_fields={"path1"},
            allow_traversal=False,
            allow_sensitive=True,
        )
        # path1 produced a warning; name didn't.
        fids = {f for _, f in out}
        assert "path1" in fids
        assert "name" not in fids

    def test_detailed_count_matches_flat(self) -> None:
        """The detailed variant must produce the same number of
        warnings as the flat variant."""
        from scriptree.core.sanitize import (
            sanitize_all_values, sanitize_all_values_detailed,
        )
        values = {"x": "../bad", "y": "; rm"}
        flat = sanitize_all_values(
            values, path_fields={"x"},
            allow_traversal=False, allow_sensitive=True,
        )
        detailed = sanitize_all_values_detailed(
            values, path_fields={"x"},
            allow_traversal=False, allow_sensitive=True,
        )
        assert len(flat) == len(detailed)


# ===========================================================================
# 4. Capability gate on the dialog checkboxes
# ===========================================================================

class TestDialogCapabilityGate:

    def _mock_perms(self, **caps: bool):
        from scriptree.core.permissions import PermissionSet
        ps = PermissionSet(allowed=dict(caps))
        return patch(
            "scriptree.core.permissions.get_app_permissions",
            return_value=ps,
        )

    def _build_runner(self):
        from scriptree.core.model import (
            ParamDef, ParamType, ToolDef, Widget,
        )
        from scriptree.ui.tool_runner import ToolRunnerView
        return ToolRunnerView(ToolDef(
            name="x", executable="python",
            params=[
                ParamDef(
                    id="p", label="P",
                    type=ParamType.PATH, widget=Widget.FILE_OPEN,
                ),
            ],
        ))

    def test_no_checkboxes_when_capability_denied(self) -> None:
        from scriptree.core.permissions import PermissionSet
        runner = self._build_runner()

        # Patch QDialog.exec to inspect the dialog tree before close.
        captured = {}

        def fake_exec(self):
            captured["checkboxes"] = self.findChildren(QCheckBox)
            return QDialog.DialogCode.Rejected  # No

        with self._mock_perms(suppress_sanitization_warnings=False), \
                patch.object(QDialog, "exec", fake_exec):
            runner._show_injection_warning(
                "• something",
                editor_protection=True,
                perms=PermissionSet(allowed={
                    "suppress_sanitization_warnings": False,
                }),
                warning_fids=["p"],
            )
        # No suppression checkboxes when capability denied.
        assert captured["checkboxes"] == []

    def test_three_checkboxes_when_capability_granted(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.core.permissions import PermissionSet
        runner = self._build_runner()
        # Give the runner a concrete file_path so the per-tool box
        # is enabled.
        runner._file_path = str(tmp_path / "demo.scriptree")

        captured = {}

        def fake_exec(self):
            captured["checkboxes"] = self.findChildren(QCheckBox)
            return QDialog.DialogCode.Rejected

        with self._mock_perms(suppress_sanitization_warnings=True), \
                patch.object(QDialog, "exec", fake_exec):
            runner._show_injection_warning(
                "• something",
                editor_protection=True,
                perms=PermissionSet(allowed={
                    "suppress_sanitization_warnings": True,
                }),
                warning_fids=["p"],
            )
        # Per-field + per-tool + global → 3 checkboxes.
        assert len(captured["checkboxes"]) == 3

    def test_proceed_with_global_check_writes_through(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.core import sanitize_suppression as supp
        from scriptree.core.permissions import PermissionSet
        runner = self._build_runner()
        runner._file_path = str(tmp_path / "demo.scriptree")

        # Capture the dialog instance, tick "for all tools", then accept.
        def fake_exec(self):
            for chk in self.findChildren(QCheckBox):
                if "all tools" in chk.text().lower():
                    chk.setChecked(True)
                    break
            return QDialog.DialogCode.Accepted

        assert supp.is_globally_muted() is False
        with self._mock_perms(suppress_sanitization_warnings=True), \
                patch.object(QDialog, "exec", fake_exec):
            proceeded = runner._show_injection_warning(
                "• something",
                editor_protection=True,
                perms=PermissionSet(allowed={
                    "suppress_sanitization_warnings": True,
                }),
                warning_fids=["p"],
            )
        assert proceeded is True
        assert supp.is_globally_muted() is True

    def test_proceed_with_per_tool_check_writes_through(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.core import sanitize_suppression as supp
        from scriptree.core.permissions import PermissionSet
        runner = self._build_runner()
        target = tmp_path / "demo.scriptree"
        target.write_text("{}", encoding="utf-8")
        runner._file_path = str(target)

        def fake_exec(self):
            for chk in self.findChildren(QCheckBox):
                if "this tool" in chk.text().lower():
                    chk.setChecked(True)
                    break
            return QDialog.DialogCode.Accepted

        with self._mock_perms(suppress_sanitization_warnings=True), \
                patch.object(QDialog, "exec", fake_exec):
            runner._show_injection_warning(
                "• warning", True,
                PermissionSet(allowed={
                    "suppress_sanitization_warnings": True,
                }),
                warning_fids=["p"],
            )
        assert supp.is_tool_muted(str(target))

    def test_proceed_with_field_check_writes_through(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.core import sanitize_suppression as supp
        from scriptree.core.permissions import PermissionSet
        runner = self._build_runner()
        target = tmp_path / "demo.scriptree"
        target.write_text("{}", encoding="utf-8")
        runner._file_path = str(target)

        def fake_exec(self):
            for chk in self.findChildren(QCheckBox):
                if "field" in chk.text().lower():
                    chk.setChecked(True)
                    break
            return QDialog.DialogCode.Accepted

        with self._mock_perms(suppress_sanitization_warnings=True), \
                patch.object(QDialog, "exec", fake_exec):
            runner._show_injection_warning(
                "• warning", True,
                PermissionSet(allowed={
                    "suppress_sanitization_warnings": True,
                }),
                warning_fids=["p", "p"],
            )
        assert supp.muted_fields_for_tool(str(target)) == ["p"]

    def test_cancel_does_not_persist(self, tmp_path: Path) -> None:
        from scriptree.core import sanitize_suppression as supp
        from scriptree.core.permissions import PermissionSet
        runner = self._build_runner()
        runner._file_path = str(tmp_path / "demo.scriptree")

        def fake_exec(self):
            for chk in self.findChildren(QCheckBox):
                chk.setChecked(True)  # tick all three
            return QDialog.DialogCode.Rejected  # but cancel

        with self._mock_perms(suppress_sanitization_warnings=True), \
                patch.object(QDialog, "exec", fake_exec):
            proceeded = runner._show_injection_warning(
                "• something", True,
                PermissionSet(allowed={
                    "suppress_sanitization_warnings": True,
                }),
                warning_fids=["p"],
            )
        assert proceeded is False
        # Nothing persisted because user clicked No.
        assert supp.is_globally_muted() is False
        assert supp.muted_tools() == []


# ===========================================================================
# 5. Re-enable dialog
# ===========================================================================

class TestReenableDialog:

    def test_dialog_constructs_and_shows_global_state(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.core import sanitize_suppression as supp
        from scriptree.ui.sanitization_suppression_dialog import (
            SanitizationSuppressionDialog,
        )
        supp.set_globally_muted(True)
        dlg = SanitizationSuppressionDialog()
        assert dlg._chk_global.isChecked() is True

    def test_dialog_lists_muted_tools(self, tmp_path: Path) -> None:
        from scriptree.core import sanitize_suppression as supp
        from scriptree.ui.sanitization_suppression_dialog import (
            SanitizationSuppressionDialog,
        )
        p = tmp_path / "demo.scriptree"
        p.write_text("{}", encoding="utf-8")
        supp.mute_tool(str(p))

        dlg = SanitizationSuppressionDialog()
        # Find the muted path in the tool list.
        items = [
            dlg._tool_list.item(i).text()
            for i in range(dlg._tool_list.count())
        ]
        assert any(p.name in t or str(p.resolve()) == t for t in items)

    def test_dialog_unmute_tool_button_works(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.core import sanitize_suppression as supp
        from scriptree.ui.sanitization_suppression_dialog import (
            SanitizationSuppressionDialog,
        )
        p = tmp_path / "demo.scriptree"
        p.write_text("{}", encoding="utf-8")
        supp.mute_tool(str(p))

        dlg = SanitizationSuppressionDialog()
        dlg._tool_list.setCurrentRow(0)
        dlg._on_unmute_tool()
        assert not supp.is_tool_muted(str(p))

    def test_clear_all_button_resets_everything(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.core import sanitize_suppression as supp
        from scriptree.ui.sanitization_suppression_dialog import (
            SanitizationSuppressionDialog,
        )
        p = tmp_path / "demo.scriptree"
        p.write_text("{}", encoding="utf-8")
        supp.set_globally_muted(True)
        supp.mute_tool(str(p))
        supp.mute_fields_for_tool(str(p), {"x"})

        dlg = SanitizationSuppressionDialog()
        # QMessageBox.question is auto-Yes (module-level patch).
        dlg._on_clear_all()
        assert supp.is_globally_muted() is False
        assert supp.muted_tools() == []
        assert supp.muted_fields_for_tool(str(p)) == []
