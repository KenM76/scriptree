"""Phase-3 regression suite for the tool-editor's per-OS
overrides widget (``scriptree.ui.platform_overrides_widget``).

Verifies the widget's data-binding contract:

* ``load_from_tool`` rebuilds tabs from ``tool.platforms``.
* ``apply_to_tool`` writes tab state back into ``tool.platforms``.
* Round-trip (load → no edits → apply) preserves the ``platforms``
  map byte-for-byte.
* Empty / preserved-field handling (env + actions stay attached
  across load → apply even though the widget doesn't expose
  them as editable fields).
* ``refresh_inherited`` updates the read-only preview rows
  without touching any tab's editable state.
* ``current_preview_os`` returns the combo's selection.
* The ``changed`` signal fires on any user-equivalent mutation.

Auto-dismisses ``QMessageBox`` per the standing rule.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

from scriptree.core.model import ActionDef, PlatformOverride, ToolDef
from scriptree.ui.platform_overrides_widget import (
    PlatformOverridesWidget,
)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _tool() -> ToolDef:
    return ToolDef(
        name="X",
        executable="py.exe",
        argument_template=["-3", "./tool.py"],
        path_prepend=["C:/Tools"],
    )


# ============================================================================
# load_from_tool
# ============================================================================


class TestLoad:
    def test_no_overrides_all_toggles_off(self) -> None:
        w = PlatformOverridesWidget()
        w.load_from_tool(_tool())
        for os_id, tab in w._os_tabs.items():
            assert tab._override_cb.isChecked() is False

    def test_macos_override_toggle_on_and_fields_populated(self) -> None:
        t = _tool()
        t.platforms["macos"] = PlatformOverride(
            executable="/usr/bin/osascript",
            argument_template=["-e", "display dialog"],
        )
        w = PlatformOverridesWidget()
        w.load_from_tool(t)

        mac = w._os_tabs["macos"]
        assert mac._override_cb.isChecked() is True
        assert mac._exe_edit.text() == "/usr/bin/osascript"
        # Template text uses the editor's line-per-entry format.
        assert "-e" in mac._argv_edit.toPlainText()

    def test_inherited_preview_populated(self) -> None:
        """The read-only preview rows show the top-level
        defaults so the author knows what each OS would
        inherit without an override."""
        t = _tool()
        w = PlatformOverridesWidget()
        w.load_from_tool(t)

        win = w._os_tabs["windows"]
        assert "py.exe" in win._inherit_exe.text()
        assert "-3" in win._inherit_argv.text()


# ============================================================================
# apply_to_tool
# ============================================================================


class TestApply:
    def test_unchecked_tabs_drop_entries(self) -> None:
        """A tab whose override toggle is off causes the OS to
        be removed from ``tool.platforms`` (vs preserved with
        an empty override)."""
        t = _tool()
        t.platforms["macos"] = PlatformOverride(
            executable="python3",
        )
        w = PlatformOverridesWidget()
        w.load_from_tool(t)

        # Untick the macos toggle and apply.
        w._os_tabs["macos"]._override_cb.setChecked(False)
        w.apply_to_tool(t)

        assert "macos" not in t.platforms

    def test_checked_tab_writes_override(self) -> None:
        t = _tool()
        w = PlatformOverridesWidget()
        w.load_from_tool(t)

        # Tick macos, set executable, apply.
        mac = w._os_tabs["macos"]
        mac._override_cb.setChecked(True)
        mac._exe_edit.setText("python3")
        w.apply_to_tool(t)

        assert "macos" in t.platforms
        assert t.platforms["macos"].executable == "python3"
        # Unset fields stay None.
        assert t.platforms["macos"].argument_template is None
        assert t.platforms["macos"].path_prepend is None

    def test_empty_fields_become_none_on_override(self) -> None:
        """The override toggle is on, but the author left all
        fields empty: every field maps to None (inherit
        default), not to empty strings/lists."""
        t = _tool()
        w = PlatformOverridesWidget()
        w.load_from_tool(t)

        mac = w._os_tabs["macos"]
        mac._override_cb.setChecked(True)
        # leave _exe_edit empty etc.
        w.apply_to_tool(t)

        assert "macos" in t.platforms
        assert t.platforms["macos"].executable is None
        assert t.platforms["macos"].argument_template is None
        assert t.platforms["macos"].path_prepend is None


# ============================================================================
# Round-trip: load → no edits → apply preserves the map
# ============================================================================


class TestRoundTrip:
    def test_load_apply_preserves_executable_override(self) -> None:
        t = _tool()
        t.platforms["linux"] = PlatformOverride(executable="python3")

        w = PlatformOverridesWidget()
        w.load_from_tool(t)
        w.apply_to_tool(t)

        assert "linux" in t.platforms
        assert t.platforms["linux"].executable == "python3"

    def test_preserved_env_and_actions_survive(self) -> None:
        """The Phase-3 UI doesn't show env / actions per-OS
        editing, but ``load → apply`` must preserve any values
        that were on the override -- otherwise a tool that
        already had per-OS env entries would silently lose
        them on the first save through the editor."""
        t = _tool()
        action = ActionDef(id="hi", label="Hi", argv=["echo", "hi"])
        t.platforms["macos"] = PlatformOverride(
            executable="osascript",
            env={"LC_ALL": "en_US.UTF-8"},
            actions=[action],
        )

        w = PlatformOverridesWidget()
        w.load_from_tool(t)
        w.apply_to_tool(t)

        mac = t.platforms["macos"]
        assert mac.executable == "osascript"
        assert mac.env == {"LC_ALL": "en_US.UTF-8"}
        assert mac.actions is not None
        assert len(mac.actions) == 1
        assert mac.actions[0].id == "hi"


# ============================================================================
# refresh_inherited
# ============================================================================


class TestRefreshInherited:
    def test_refresh_updates_preview_rows(self) -> None:
        t = _tool()
        w = PlatformOverridesWidget()
        w.load_from_tool(t)

        # Simulate the editor's top-level fields changing.
        w.refresh_inherited(
            executable="python3.12",
            argument_template_text="-m mytool",
            path_prepend=["/opt/bin"],
        )

        for tab in w._os_tabs.values():
            assert tab._inherit_exe.text() == "python3.12"
            assert "mytool" in tab._inherit_argv.text()
            assert "/opt/bin" in tab._inherit_paths.text()

    def test_refresh_does_not_clobber_override_edits(self) -> None:
        """An in-progress edit on the override side must
        survive a refresh of the inherited preview."""
        t = _tool()
        w = PlatformOverridesWidget()
        w.load_from_tool(t)

        mac = w._os_tabs["macos"]
        mac._override_cb.setChecked(True)
        mac._exe_edit.setText("in-progress-exe")

        w.refresh_inherited(
            executable="WOULDNT-MATCH",
            argument_template_text="",
            path_prepend=[],
        )

        # The override edit is intact.
        assert mac._exe_edit.text() == "in-progress-exe"


# ============================================================================
# Misc
# ============================================================================


class TestMisc:
    def test_current_preview_os_returns_combo_selection(self) -> None:
        w = PlatformOverridesWidget()
        # Find the index of "linux" in the combo and select it.
        for i in range(w._preview_combo.count()):
            if w._preview_combo.itemData(i) == "linux":
                w._preview_combo.setCurrentIndex(i)
                break
        assert w.current_preview_os() == "linux"

    def test_changed_signal_fires_on_toggle(self) -> None:
        w = PlatformOverridesWidget()
        fires: list[int] = []
        w.changed.connect(lambda: fires.append(1))

        # Toggle the macos override -- should emit changed.
        w._os_tabs["macos"]._override_cb.setChecked(True)
        # Block-signals during load_from_tool means we expect
        # at least one direct user-equivalent emission here.
        assert fires, (
            "changed signal didn't fire on a programmatic toggle "
            "that mimics user interaction."
        )

    def test_preview_os_signal_fires_on_combo_change(self) -> None:
        w = PlatformOverridesWidget()
        emitted: list[str] = []
        w.previewOsChanged.connect(lambda os_id: emitted.append(os_id))

        # Pick the "linux" index.
        for i in range(w._preview_combo.count()):
            if w._preview_combo.itemData(i) == "linux":
                w._preview_combo.setCurrentIndex(i)
                break
        assert "linux" in emitted
