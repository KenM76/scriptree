"""Tests for forest login-autostart (v0.8.0a84).

The forest gained the tree-ring's "Auto-load on startup" capability: a
Windows Run-key that launches ScripTree in forest mode at login and loads
the configured forest.  Because ScripTree is single-instance, ring-autostart
and forest-autostart must share ONE Run-key value per scope, so the command
is built by a single unified builder and written through one chokepoint
(``ring_io.recompute_autostart``).

These tests cover, WITHOUT touching the real registry or %APPDATA%:

  T1  ``_build_autostart_cmd_combined`` truth table + byte-equality of the
      ring-only path with the historic ``_build_autostart_cmd``.
  T2  ``ForestPreferences.autostart_scope`` round-trip, legacy-file default,
      invalid-value clamp, and ``normalised()`` preservation.
  T3  ``recompute_autostart`` register-vs-unregister for all four
      (rings × forest) combinations.
  T4  ``set_forest_autostart`` / ``disable_forest_autostart`` semantics
      (scope, default_forest_path, fallback, and which scopes recompute).
  T5  Ring-autostart regression guard: routing ``add_autoload_ring`` /
      ``remove_autoload_ring`` through ``recompute_autostart`` keeps the
      ring-only command byte-identical and still unregisters when empty —
      unless forest autostart keeps the Run-key alive.

All registry writes are intercepted by monkeypatching
``register_autostart`` / ``unregister_autostart`` (or ``recompute_autostart``)
to in-memory recorders, so the suite runs on any platform.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from PySide6.QtWidgets import QApplication

# A QApplication must exist before any QWidget/QMenu/QDialog is built (the
# menu/dialog regression tests below).  Reuse the process-wide instance.
_app = QApplication.instance() or QApplication([])

from scriptree.shell.branding_loader import load_branding
from scriptree.shell.cell_registry import CellRegistry
from scriptree.shell.forest_io import ForestDef


def _branding() -> dict:
    return load_branding()


def _fresh_registry() -> CellRegistry:
    """Close any cells/masters left over from a prior test so the forest
    controller starts from a clean slate (mirrors test_forest.py)."""
    reg = CellRegistry.instance()
    for h in list(reg.standalones()) + list(reg.masters()):
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    return reg


def _all_menu_actions(menu) -> list:
    """Flatten a QMenu tree into every QAction it contains (recursing into
    submenus) so a test can locate an action by label without knowing the
    exact submenu nesting."""
    out = []
    for act in menu.actions():
        out.append(act)
        sub = act.menu()
        if sub is not None:
            out.extend(_all_menu_actions(sub))
    return out


# ---------------------------------------------------------------------------
# T1 — the unified command builder (pure; no registry, no disk)
# ---------------------------------------------------------------------------

class TestUnifiedAutostartCommand:
    def test_ring_only_is_byte_identical_to_legacy(self) -> None:
        from scriptree.shell.ring_io import (
            _build_autostart_cmd, _build_autostart_cmd_combined,
        )
        combined = _build_autostart_cmd_combined(forest=False, rings=True)
        assert combined == _build_autostart_cmd()
        assert "--autoload-rings" in combined
        assert "--forest" not in combined
        assert combined.startswith(f'"{sys.executable}" -m scriptree.shell.ring_main')

    def test_forest_and_rings_has_both_flags_forest_first(self) -> None:
        from scriptree.shell.ring_io import _build_autostart_cmd_combined
        cmd = _build_autostart_cmd_combined(forest=True, rings=True)
        assert "--forest" in cmd and "--autoload-rings" in cmd
        # --forest must come before --autoload-rings.
        assert cmd.index("--forest") < cmd.index("--autoload-rings")
        assert cmd.startswith(f'"{sys.executable}" -m scriptree.shell.ring_main')

    def test_forest_only_has_no_autoload_rings(self) -> None:
        from scriptree.shell.ring_io import _build_autostart_cmd_combined
        cmd = _build_autostart_cmd_combined(forest=True, rings=False)
        assert "--forest" in cmd
        assert "--autoload-rings" not in cmd
        assert cmd.startswith(f'"{sys.executable}" -m scriptree.shell.ring_main')


# ---------------------------------------------------------------------------
# T2 — preferences round-trip / legacy / clamp
# ---------------------------------------------------------------------------

class TestAutostartScopePersistence:
    def _redirect(self, tmp_path: Path, monkeypatch: Any) -> Path:
        from scriptree.shell import forest_io as io_mod
        prefs_file = tmp_path / "forest_preferences.json"
        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: prefs_file,
        )
        return prefs_file

    def test_factory_default_is_off(self, tmp_path: Path, monkeypatch: Any) -> None:
        from scriptree.shell.forest_io import load_preferences
        self._redirect(tmp_path, monkeypatch)
        assert load_preferences(_branding()).autostart_scope == "off"

    def test_round_trip_system(self, tmp_path: Path, monkeypatch: Any) -> None:
        from scriptree.shell.forest_io import (
            ForestPreferences, load_preferences, save_preferences,
        )
        self._redirect(tmp_path, monkeypatch)
        save_preferences(
            ForestPreferences(autostart_scope="system"), _branding(),
        )
        assert load_preferences(_branding()).autostart_scope == "system"

    def test_legacy_file_without_key_loads_off(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        import json
        from scriptree.shell.forest_io import (
            load_preferences, _PREFS_FORMAT, _PREFS_VERSION,
        )
        prefs_file = self._redirect(tmp_path, monkeypatch)
        # A pre-a84 prefs blob — no autostart_scope key at all.
        prefs_file.write_text(json.dumps({
            "format": _PREFS_FORMAT,
            "version": _PREFS_VERSION,
            "fallback_to_default": True,
            "default_forest_path": "",
            "show_always_on_top": True,
            "show_on_taskbar": False,
            "show_in_system_tray": False,
        }), encoding="utf-8")
        assert load_preferences(_branding()).autostart_scope == "off"

    def test_invalid_value_clamps_to_off(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        import json
        from scriptree.shell.forest_io import (
            load_preferences, _PREFS_FORMAT, _PREFS_VERSION,
        )
        prefs_file = self._redirect(tmp_path, monkeypatch)
        prefs_file.write_text(json.dumps({
            "format": _PREFS_FORMAT,
            "version": _PREFS_VERSION,
            "autostart_scope": "everyone-lol",
        }), encoding="utf-8")
        assert load_preferences(_branding()).autostart_scope == "off"

    def test_normalised_preserves_scope_on_visibility_repair(self) -> None:
        from scriptree.shell.forest_io import ForestPreferences
        # All visibility flags False triggers the repair constructor; the
        # autostart_scope must survive it (else a hand-edited file silently
        # disables/changes login autostart).
        p = ForestPreferences(
            show_always_on_top=False,
            show_on_taskbar=False,
            show_in_system_tray=False,
            autostart_scope="user",
        ).normalised()
        assert p.show_always_on_top is True  # repaired
        assert p.autostart_scope == "user"   # preserved


# ---------------------------------------------------------------------------
# T3 — recompute_autostart truth table
# ---------------------------------------------------------------------------

class TestRecomputeAutostart:
    def _wire(self, monkeypatch: Any, *, rings: bool, forest: bool):
        """Patch the chokepoint's three inputs + capture register/unregister."""
        from scriptree.shell import ring_io as rio
        calls: dict[str, Any] = {"register": [], "unregister": []}
        monkeypatch.setattr(
            rio, "list_autoload_rings",
            lambda scope: ([Path("r.scriptreering")] if rings else []),
        )
        monkeypatch.setattr(rio, "_forest_autostart_on", lambda scope: forest)
        monkeypatch.setattr(
            rio, "register_autostart",
            lambda scope, cmd, brand=None: calls["register"].append((scope, cmd)),
        )
        monkeypatch.setattr(
            rio, "unregister_autostart",
            lambda scope, brand=None: calls["unregister"].append(scope),
        )
        return rio, calls

    def test_neither_unregisters(self, monkeypatch: Any) -> None:
        rio, calls = self._wire(monkeypatch, rings=False, forest=False)
        rio.recompute_autostart("user")
        assert calls["unregister"] == ["user"]
        assert calls["register"] == []

    def test_rings_only_registers_legacy_cmd(self, monkeypatch: Any) -> None:
        rio, calls = self._wire(monkeypatch, rings=True, forest=False)
        rio.recompute_autostart("user")
        assert calls["unregister"] == []
        assert len(calls["register"]) == 1
        scope, cmd = calls["register"][0]
        assert scope == "user"
        assert cmd == rio._build_autostart_cmd()  # byte-identical
        assert "--forest" not in cmd

    def test_forest_only_registers_forest_cmd(self, monkeypatch: Any) -> None:
        rio, calls = self._wire(monkeypatch, rings=False, forest=True)
        rio.recompute_autostart("system")
        scope, cmd = calls["register"][0]
        assert scope == "system"
        assert "--forest" in cmd and "--autoload-rings" not in cmd

    def test_both_registers_combined_cmd(self, monkeypatch: Any) -> None:
        rio, calls = self._wire(monkeypatch, rings=True, forest=True)
        rio.recompute_autostart("user")
        _scope, cmd = calls["register"][0]
        assert "--forest" in cmd and "--autoload-rings" in cmd


# ---------------------------------------------------------------------------
# T4 — set_forest_autostart / disable_forest_autostart
# ---------------------------------------------------------------------------

class TestForestAutostartHelpers:
    def _wire(self, tmp_path: Path, monkeypatch: Any):
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell import ring_io as rio
        prefs_file = tmp_path / "forest_preferences.json"
        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: prefs_file,
        )
        recomputed: list[str] = []
        monkeypatch.setattr(
            rio, "recompute_autostart",
            lambda scope: recomputed.append(scope),
        )
        return io_mod, recomputed

    def test_set_user_from_off(self, tmp_path: Path, monkeypatch: Any) -> None:
        io_mod, recomputed = self._wire(tmp_path, monkeypatch)
        forest_file = tmp_path / "my.scriptreeforest"
        forest_file.write_text("{}", encoding="utf-8")
        io_mod.set_forest_autostart(
            "user", _branding(), forest_path=str(forest_file),
        )
        prefs = io_mod.load_preferences(_branding())
        assert prefs.autostart_scope == "user"
        assert prefs.default_forest_path == str(forest_file.resolve())
        assert prefs.fallback_to_default is True
        # off → user touches only the user scope.
        assert recomputed == ["user"]

    def test_set_system_from_user_recomputes_old_scope(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        io_mod, recomputed = self._wire(tmp_path, monkeypatch)
        forest_file = tmp_path / "my.scriptreeforest"
        forest_file.write_text("{}", encoding="utf-8")
        io_mod.set_forest_autostart("user", _branding(), forest_path=str(forest_file))
        recomputed.clear()
        io_mod.set_forest_autostart("system", _branding(), forest_path=str(forest_file))
        assert io_mod.load_preferences(_branding()).autostart_scope == "system"
        # Moving scopes recomputes the NEW scope and the OLD one.
        assert set(recomputed) == {"system", "user"}

    def test_disable_clears_scope_keeps_path(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        io_mod, recomputed = self._wire(tmp_path, monkeypatch)
        forest_file = tmp_path / "my.scriptreeforest"
        forest_file.write_text("{}", encoding="utf-8")
        io_mod.set_forest_autostart("user", _branding(), forest_path=str(forest_file))
        recomputed.clear()
        io_mod.disable_forest_autostart(_branding())
        prefs = io_mod.load_preferences(_branding())
        assert prefs.autostart_scope == "off"
        # default_forest_path is left intact (in-app default is independent).
        assert prefs.default_forest_path == str(forest_file.resolve())
        # disable recomputes ONLY the previously-active scope (here "user").
        # Recomputing "system" too would raise PermissionError on the HKLM
        # admin check during an unelevated user→off disable (adversarial
        # finding #1) — so it must NOT be touched.
        assert recomputed == ["user"]

    def test_disable_from_off_recomputes_nothing(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        # old_scope already "off": there is no Run-key carrying --forest, so
        # disable must not recompute (and definitely not touch system/HKLM).
        io_mod, recomputed = self._wire(tmp_path, monkeypatch)
        io_mod.disable_forest_autostart(_branding())
        assert io_mod.load_preferences(_branding()).autostart_scope == "off"
        assert recomputed == []


# ---------------------------------------------------------------------------
# T5 — ring-autostart regression guard (forest off → unchanged)
# ---------------------------------------------------------------------------

class TestRingAutostartRegression:
    def _wire(self, tmp_path: Path, monkeypatch: Any, *, forest_on: bool):
        from scriptree.shell import ring_io as rio
        # Redirect the ring autoload JSON to tmp so we don't touch %APPDATA%.
        cfg = {"path": None}
        def _cfg_path(brand, scope):
            return tmp_path / f"autoload_rings_{scope}.json"
        monkeypatch.setattr(rio, "_autoload_config_path", _cfg_path)
        monkeypatch.setattr(rio, "_forest_autostart_on", lambda scope: forest_on)
        calls: dict[str, Any] = {"register": [], "unregister": []}
        monkeypatch.setattr(
            rio, "register_autostart",
            lambda scope, cmd, brand=None: calls["register"].append((scope, cmd)),
        )
        monkeypatch.setattr(
            rio, "unregister_autostart",
            lambda scope, brand=None: calls["unregister"].append(scope),
        )
        return rio, calls

    def test_add_ring_registers_legacy_cmd(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        rio, calls = self._wire(tmp_path, monkeypatch, forest_on=False)
        rio.add_autoload_ring(tmp_path / "a.scriptreering", "user")
        assert len(calls["register"]) == 1
        scope, cmd = calls["register"][0]
        assert scope == "user"
        assert cmd == rio._build_autostart_cmd()

    def test_remove_last_ring_unregisters_when_forest_off(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        rio, calls = self._wire(tmp_path, monkeypatch, forest_on=False)
        ring = tmp_path / "a.scriptreering"
        rio.add_autoload_ring(ring, "user")
        calls["register"].clear()
        rio.remove_autoload_ring(ring, "user")
        assert calls["unregister"] == ["user"]
        assert calls["register"] == []

    def test_remove_last_ring_keeps_forest_cmd_when_forest_on(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        rio, calls = self._wire(tmp_path, monkeypatch, forest_on=True)
        ring = tmp_path / "a.scriptreering"
        rio.add_autoload_ring(ring, "user")
        calls["register"].clear()
        calls["unregister"].clear()
        rio.remove_autoload_ring(ring, "user")
        # Forest still wants autostart → keep a --forest-only Run-key, not unregister.
        assert calls["unregister"] == []
        assert len(calls["register"]) == 1
        _scope, cmd = calls["register"][0]
        assert "--forest" in cmd and "--autoload-rings" not in cmd


# ---------------------------------------------------------------------------
# Regression guards for the two adversarial-review findings (a84)
# ---------------------------------------------------------------------------

class TestVisibilityToggleDoesNotResetAutostart:
    """Adversarial finding #1 (HIGH): toggling a visibility option in the
    forest menu rebuilt ``ForestPreferences`` WITHOUT ``autostart_scope``,
    silently resetting it to "off" on disk while the Run-key still carried
    ``--forest`` (UI says Disabled but it still autostarts at login, with no
    cleanup path).  Drive the real menu toggle and assert the scope survives.
    """

    def _redirect(self, tmp_path: Path, monkeypatch: Any) -> None:
        from scriptree.shell import forest_io as io_mod
        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: tmp_path / "forest_preferences.json",
        )

    def test_toggle_taskbar_preserves_autostart_scope(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        from PySide6.QtWidgets import QMenu
        from scriptree.shell.forest_controller import ForestController
        from scriptree.shell.forest_io import (
            ForestPreferences, load_preferences, save_preferences,
        )

        self._redirect(tmp_path, monkeypatch)
        # Seed prefs: autostart enabled for the user, taskbar OFF (so toggling
        # it ON is an ALLOWED change — at least one visibility flag stays set).
        save_preferences(
            ForestPreferences(
                autostart_scope="user",
                show_always_on_top=True,
                show_on_taskbar=False,
                show_in_system_tray=False,
            ),
            _branding(),
        )

        _fresh_registry()
        ctrl = ForestController(_branding(), CellRegistry.instance(), None)
        ctrl.set_autosave_enabled(False)
        ctrl.start(forest=ForestDef(), suppress_first_run=True)
        # Make the prefs the controller holds match what we saved, then null the
        # visibility manager so update_preferences' live-apply doesn't spawn a
        # taskbar/tray host — we are testing the PREFS WRITE, not the apply.
        ctrl._preferences = load_preferences(_branding())
        ctrl._visibility = None
        assert ctrl.get_preferences().autostart_scope == "user"

        menu = QMenu()
        ctrl.forest_window._forest_menu_extension(menu)
        actions = _all_menu_actions(menu)
        taskbar = next(a for a in actions if a.text() == "Show on taskbar")
        assert taskbar.isChecked() is False
        # Firing setChecked emits ``toggled`` → ``_on_visibility_toggle`` →
        # update_preferences (the bug site).
        taskbar.setChecked(True)

        # Before the fix this asserted "off"; after the fix the scope persists.
        assert load_preferences(_branding()).autostart_scope == "user"
        ctrl.forest_window.close()


class TestSettingsDialogAutostartComboPreservesPath:
    """Adversarial finding #2 (MEDIUM): enabling autostart via the settings
    dialog combo rewrote ``default_forest_path``/``fallback_to_default`` on
    disk, but the dialog's seeded Launch-defaults widgets were never refreshed,
    so a subsequent Save wrote the stale values back and clobbered the path.
    """

    def _redirect(self, tmp_path: Path, monkeypatch: Any) -> None:
        from scriptree.shell import forest_io as io_mod
        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: tmp_path / "forest_preferences.json",
        )

    def test_combo_enable_then_save_keeps_forest_path(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        from scriptree.shell import ring_io as rio
        from scriptree.shell.forest_controller import ForestController
        from scriptree.shell.forest_dialogs import ForestSettingsDialog
        from scriptree.shell.forest_io import load_preferences

        self._redirect(tmp_path, monkeypatch)
        # Intercept the Run-key recompute so the test never touches the registry.
        monkeypatch.setattr(rio, "recompute_autostart", lambda scope: None)

        forest_file = tmp_path / "ws.scriptreeforest"
        forest_file.write_text("{}", encoding="utf-8")

        _fresh_registry()
        ctrl = ForestController(_branding(), CellRegistry.instance(), None)
        ctrl.set_autosave_enabled(False)
        ctrl.start(forest=ForestDef(), suppress_first_run=True)
        ctrl._visibility = None
        # Pretend this forest is saved so the combo's live-apply doesn't pop a
        # "save first" prompt.
        ctrl.forest.loaded_from = str(forest_file)

        dlg = ForestSettingsDialog(ctrl)
        # Select "For current user only" (index 1) — fires the live-apply.
        dlg._autostart_combo.setCurrentIndex(1)

        resolved = str(forest_file.resolve())
        # The dialog's path widget was refreshed to the autostart-configured
        # forest (the finding-#2 fix), not left at its stale construction value.
        assert dlg._prefs_path_edit.text() == resolved
        assert dlg._prefs_fallback_cb.isChecked() is True

        # Saving must NOT clobber the path autostart configured.
        dlg._save()
        prefs = load_preferences(_branding())
        assert prefs.autostart_scope == "user"
        assert prefs.default_forest_path == resolved
        assert prefs.fallback_to_default is True


class TestElevationCancelDoesNotFlipScope:
    """Adversarial finding #2 (MEDIUM): the elevate helpers swallowed a UAC
    cancel (ShellExecuteW ≤ 32) and the controller flipped the cached scope
    optimistically regardless, so the menu claimed a scope nothing ever wrote.
    The helpers now return success; the controller flips only on True.
    """

    def _redirect(self, tmp_path: Path, monkeypatch: Any) -> None:
        from scriptree.shell import forest_io as io_mod
        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: tmp_path / "forest_preferences.json",
        )

    def _make_ctrl(self, tmp_path: Path):
        from scriptree.shell.forest_controller import ForestController
        forest_file = tmp_path / "ws.scriptreeforest"
        forest_file.write_text("{}", encoding="utf-8")
        _fresh_registry()
        ctrl = ForestController(_branding(), CellRegistry.instance(), None)
        ctrl.set_autosave_enabled(False)
        ctrl.start(forest=ForestDef(), suppress_first_run=True)
        ctrl._visibility = None
        ctrl.forest.loaded_from = str(forest_file)
        return ctrl

    def test_system_enable_uac_cancel_keeps_scope_off(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        from scriptree.shell import ring_io as rio
        self._redirect(tmp_path, monkeypatch)
        # Simulate: not admin, UAC cancelled (elevate returns False).
        monkeypatch.setattr(rio, "_is_admin", lambda: False)
        monkeypatch.setattr(
            rio, "elevate_for_forest_autostart_system", lambda p: False,
        )
        ctrl = self._make_ctrl(tmp_path)
        assert ctrl.get_preferences().autostart_scope == "off"
        ctrl._on_forest_autostart_set("system")
        # Cancelled → nothing written → cache must NOT have flipped.
        assert ctrl.get_preferences().autostart_scope == "off"
        ctrl.forest_window.close()

    def test_system_enable_uac_accept_flips_scope(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        from scriptree.shell import ring_io as rio
        self._redirect(tmp_path, monkeypatch)
        monkeypatch.setattr(rio, "_is_admin", lambda: False)
        monkeypatch.setattr(
            rio, "elevate_for_forest_autostart_system", lambda p: True,
        )
        ctrl = self._make_ctrl(tmp_path)
        ctrl._on_forest_autostart_set("system")
        # Elevation launched → optimistic flip keeps THIS process's menu in sync.
        assert ctrl.get_preferences().autostart_scope == "system"
        ctrl.forest_window.close()

    def test_user_off_not_admin_does_not_raise(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """Finding #1 at the controller level: disabling from USER scope while
        not admin must not raise (it used to hit recompute_autostart('system')
        → PermissionError) and must land scope 'off'."""
        from scriptree.shell import ring_io as rio
        self._redirect(tmp_path, monkeypatch)
        # User scope writes HKCU only; stub register/unregister so no real
        # registry I/O, and force non-admin to exercise the inline disable.
        monkeypatch.setattr(rio, "_is_admin", lambda: False)
        monkeypatch.setattr(rio, "register_autostart", lambda *a, **k: None)
        monkeypatch.setattr(rio, "unregister_autostart", lambda *a, **k: None)
        ctrl = self._make_ctrl(tmp_path)
        # Put it in user scope first (inline, no elevation).
        ctrl._on_forest_autostart_set("user")
        assert ctrl.get_preferences().autostart_scope == "user"
        # Now disable — must not raise, must land "off".
        ctrl._on_forest_autostart_set("off")
        assert ctrl.get_preferences().autostart_scope == "off"
        ctrl.forest_window.close()
